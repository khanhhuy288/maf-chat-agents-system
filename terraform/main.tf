terraform {
  required_version = ">= 1.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }

  # Optional: Configure backend for state management
  # Uncomment and configure if you want to use remote state
  # backend "azurerm" {
  #   resource_group_name  = "terraform-state-rg"
  #   storage_account_name  = "terraformstate"
  #   container_name        = "tfstate"
  #   key                   = "container-apps.terraform.tfstate"
  # }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
    key_vault {
      purge_soft_delete_on_destroy    = true
      recover_soft_deleted_key_vaults = true
    }
  }
}

# Data source for current Azure client configuration
data "azurerm_client_config" "current" {}

# Resource Group
resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location

  tags = var.tags
}

# Log Analytics Workspace for Container Apps logging
resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.project_name}-logs"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days

  tags = var.tags
}

# Container Apps Environment
resource "azurerm_container_app_environment" "main" {
  name                       = "${var.project_name}-env"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  tags = var.tags
}

# Azure Container Registry
resource "azurerm_container_registry" "main" {
  name                = "${replace(var.project_name, "-", "")}acr"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = var.acr_sku
  admin_enabled       = var.acr_admin_enabled

  tags = var.tags
}

# Azure Key Vault for secrets
resource "azurerm_key_vault" "main" {
  name                       = "${var.project_name}-kv"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = var.key_vault_purge_protection

  # Access policy for current user
  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    secret_permissions = [
      "Get",
      "Set",
      "Delete",
      "List",
      "Purge",
      "Recover"
    ]
  }

  tags = var.tags
}

# Key Vault Secrets
resource "azurerm_key_vault_secret" "azure_openai_api_key" {
  name         = "azure-openai-api-key"
  value        = var.azure_openai_api_key
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_key_vault.main]
}

resource "azurerm_key_vault_secret" "ticket_logic_app_url" {
  name         = "ticket-logic-app-url"
  value        = var.ticket_logic_app_url
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_key_vault.main]
}

# ACR Admin credentials (only if admin is enabled)
# Note: admin_username and admin_password are only available after ACR creation
# and may change, so we ignore changes to prevent plan inconsistencies
resource "azurerm_key_vault_secret" "acr_username" {
  count        = var.acr_admin_enabled ? 1 : 0
  name         = "acr-username"
  value        = azurerm_container_registry.main.admin_username
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_container_registry.main, azurerm_key_vault.main]

  lifecycle {
    ignore_changes = [value]
  }
}

resource "azurerm_key_vault_secret" "acr_password" {
  count        = var.acr_admin_enabled ? 1 : 0
  name         = "acr-password"
  value        = azurerm_container_registry.main.admin_password
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_container_registry.main, azurerm_key_vault.main]

  lifecycle {
    ignore_changes = [value]
  }
}

# User-Assigned Managed Identity for Container App
# Using user-assigned identity avoids circular dependency issues with registry authentication
resource "azurerm_user_assigned_identity" "container_app" {
  name                = "${var.project_name}-identity"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  tags = var.tags
}

# Container App with User-Assigned Identity
resource "azurerm_container_app" "main" {
  name                         = var.project_name
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = var.revision_mode

  # User-assigned managed identity for ACR and Key Vault access
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.container_app.id]
  }

  # Ingress configuration
  ingress {
    external_enabled = true
    target_port      = var.container_port
    transport        = "http"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  # Registry configuration using identity-based authentication
  # The Container App's user-assigned managed identity is used to authenticate to ACR
  # The role assignment (azurerm_role_assignment.acr_pull) grants the identity AcrPull permission
  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.container_app.id
  }

  # Container template
  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = var.container_name
      image  = "${azurerm_container_registry.main.login_server}/${var.container_image}:${var.container_image_tag}"
      cpu    = var.container_cpu
      memory = var.container_memory

      # Environment variables
      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = var.azure_openai_endpoint
      }

      env {
        name  = "AZURE_OPENAI_API_VERSION"
        value = var.azure_openai_api_version
      }

      env {
        name  = "AZURE_OPENAI_DEPLOYMENT"
        value = var.azure_openai_deployment
      }

      env {
        name  = "AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
        value = var.azure_openai_embedding_deployment
      }

      env {
        name  = "DEFAULT_RESPONSE_LANGUAGE"
        value = var.default_response_language
      }

      # Secrets from variables (stored in Key Vault for management, passed as env vars)
      # Note: For production, consider using Key Vault secret references with two-step apply
      env {
        name  = "AZURE_OPENAI_API_KEY"
        value = var.azure_openai_api_key
      }

      env {
        name  = "TICKET_LOGIC_APP_URL"
        value = var.ticket_logic_app_url
      }

      # Health probes
      liveness_probe {
        transport               = "HTTP"
        port                    = var.container_port
        path                    = "/health"
        initial_delay           = 40
        interval_seconds        = 30
        timeout                 = 10
        failure_count_threshold = 3
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = var.container_port
        path                    = "/health"
        interval_seconds        = 10
        timeout                 = 5
        success_count_threshold = 1
        failure_count_threshold = 3
      }
    }
  }

  tags = var.tags

  depends_on = [
    azurerm_container_registry.main,
    azurerm_key_vault_secret.azure_openai_api_key,
    azurerm_key_vault_secret.ticket_logic_app_url
  ]
}

# Key Vault Access Policy for Container App Identity
# Note: This is set up for future use if you want to reference Key Vault secrets directly
# Currently, secrets are passed as environment variables for simplicity
resource "azurerm_key_vault_access_policy" "container_app" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = azurerm_user_assigned_identity.container_app.tenant_id
  object_id    = azurerm_user_assigned_identity.container_app.principal_id

  secret_permissions = [
    "Get",
    "List"
  ]
}

# Container Registry role assignment for Container App identity
# Grants the user-assigned identity permission to pull images from ACR
resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.container_app.principal_id
}

# Optional: Application Insights (if enabled)
resource "azurerm_application_insights" "main" {
  count               = var.enable_application_insights ? 1 : 0
  name                = "${var.project_name}-insights"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  application_type    = "web"

  tags = var.tags
}


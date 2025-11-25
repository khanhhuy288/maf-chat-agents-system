variable "project_name" {
  description = "Base name for all resources (must be unique, lowercase alphanumeric)"
  type        = string
  default     = "ticket-api"

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.project_name))
    error_message = "Project name must be lowercase alphanumeric with hyphens only."
  }
}

variable "location" {
  description = "Azure region for resources"
  type        = string
  default     = "westeurope"
}

variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
  default     = "ticket-rg"
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default = {
    environment = "production"
    managed_by  = "terraform"
  }
}

# Container Registry Configuration
variable "acr_sku" {
  description = "SKU for Azure Container Registry (Basic, Standard, Premium)"
  type        = string
  default     = "Basic"

  validation {
    condition     = contains(["Basic", "Standard", "Premium"], var.acr_sku)
    error_message = "ACR SKU must be Basic, Standard, or Premium."
  }
}

variable "acr_admin_enabled" {
  description = "Enable admin user for ACR. Required for Container App registry authentication. For identity-based auth, enable this initially, then can be disabled after setting up identity_id in registry block."
  type        = bool
  default     = true
}

# Container App Configuration
variable "container_name" {
  description = "Name of the container within the Container App"
  type        = string
  default     = "ticket-api"
}

variable "container_image" {
  description = "Container image name (without registry and tag)"
  type        = string
  default     = "ticket-api"
}

variable "container_image_tag" {
  description = "Container image tag"
  type        = string
  default     = "latest"
}

variable "container_port" {
  description = "Port the container listens on"
  type        = number
  default     = 8000
}

variable "container_cpu" {
  description = "CPU allocation for container (0.25, 0.5, 0.75, 1.0, etc.)"
  type        = number
  default     = 1.0
}

variable "container_memory" {
  description = "Memory allocation for container (e.g., '0.5Gi', '1.0Gi', '2.0Gi')"
  type        = string
  default     = "2.0Gi"
}

variable "revision_mode" {
  description = "Revision mode: Single or Multiple"
  type        = string
  default     = "Single"

  validation {
    condition     = contains(["Single", "Multiple"], var.revision_mode)
    error_message = "Revision mode must be Single or Multiple."
  }
}

# Scaling Configuration
variable "min_replicas" {
  description = "Minimum number of replicas"
  type        = number
  default     = 1
}

variable "max_replicas" {
  description = "Maximum number of replicas"
  type        = number
  default     = 10
}

variable "enable_http_scaling" {
  description = "Enable HTTP-based auto-scaling"
  type        = bool
  default     = true
}

variable "scale_concurrent_requests" {
  description = "Number of concurrent requests per replica before scaling"
  type        = number
  default     = 100
}

# Azure OpenAI Configuration
variable "azure_openai_endpoint" {
  description = "Azure OpenAI endpoint URL"
  type        = string
  sensitive   = false # Endpoint is not sensitive, but we mark it for clarity
}

variable "azure_openai_api_key" {
  description = "Azure OpenAI API key (will be stored in Key Vault)"
  type        = string
  sensitive   = true
}

variable "azure_openai_api_version" {
  description = "Azure OpenAI API version"
  type        = string
  default     = "2024-02-15-preview"
}

variable "azure_openai_deployment" {
  description = "Azure OpenAI deployment name"
  type        = string
  default     = "gpt-4"
}

variable "azure_openai_embedding_deployment" {
  description = "Azure OpenAI embedding deployment name"
  type        = string
  default     = "text-embedding-ada-002"
}

# Logic App Configuration
variable "ticket_logic_app_url" {
  description = "Azure Logic App webhook URL"
  type        = string
  sensitive   = true
}

variable "default_response_language" {
  description = "Default language for responses"
  type        = string
  default     = "de"
}

# Logging Configuration
variable "log_retention_days" {
  description = "Log Analytics workspace retention in days"
  type        = number
  default     = 30
}

# Key Vault Configuration
variable "key_vault_purge_protection" {
  description = "Enable purge protection on Key Vault (recommended for production)"
  type        = bool
  default     = false
}

# Application Insights
variable "enable_application_insights" {
  description = "Enable Application Insights for monitoring"
  type        = bool
  default     = false
}


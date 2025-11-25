output "resource_group_name" {
  description = "Name of the resource group"
  value       = azurerm_resource_group.main.name
}

output "container_app_name" {
  description = "Name of the Container App"
  value       = azurerm_container_app.main.name
}

output "container_app_url" {
  description = "FQDN of the Container App"
  value       = azurerm_container_app.main.latest_revision_fqdn
}

output "container_app_id" {
  description = "Resource ID of the Container App"
  value       = azurerm_container_app.main.id
}

output "container_registry_name" {
  description = "Name of the Azure Container Registry"
  value       = azurerm_container_registry.main.name
}

output "container_registry_login_server" {
  description = "Login server URL for the Container Registry"
  value       = azurerm_container_registry.main.login_server
}

output "container_registry_admin_username" {
  description = "Admin username for ACR (if admin enabled)"
  value       = var.acr_admin_enabled ? azurerm_container_registry.main.admin_username : null
  sensitive   = false
}

output "key_vault_name" {
  description = "Name of the Key Vault"
  value       = azurerm_key_vault.main.name
}

output "key_vault_uri" {
  description = "URI of the Key Vault"
  value       = azurerm_key_vault.main.vault_uri
}

output "log_analytics_workspace_id" {
  description = "ID of the Log Analytics Workspace"
  value       = azurerm_log_analytics_workspace.main.id
}

output "application_insights_instrumentation_key" {
  description = "Application Insights instrumentation key (if enabled)"
  value       = var.enable_application_insights ? azurerm_application_insights.main[0].instrumentation_key : null
  sensitive   = true
}

output "application_insights_connection_string" {
  description = "Application Insights connection string (if enabled)"
  value       = var.enable_application_insights ? azurerm_application_insights.main[0].connection_string : null
  sensitive   = true
}

output "container_app_identity_principal_id" {
  description = "Principal ID of the Container App's system-assigned identity"
  value       = azurerm_container_app.main.identity[0].principal_id
}

# Useful commands output
output "docker_login_command" {
  description = "Command to login to ACR"
  value       = "az acr login --name ${azurerm_container_registry.main.name}"
}

output "docker_build_command" {
  description = "Command to build and push image to ACR"
  value       = "az acr build --registry ${azurerm_container_registry.main.name} --image ${var.container_image}:${var.container_image_tag} --file Dockerfile.api ."
}

output "view_logs_command" {
  description = "Command to view Container App logs"
  value       = "az containerapp logs show --name ${azurerm_container_app.main.name} --resource-group ${azurerm_resource_group.main.name} --follow"
}

output "api_endpoints" {
  description = "API endpoint URLs"
  value = {
    health      = "https://${azurerm_container_app.main.latest_revision_fqdn}/health"
    ready       = "https://${azurerm_container_app.main.latest_revision_fqdn}/ready"
    docs        = "https://${azurerm_container_app.main.latest_revision_fqdn}/docs"
    redoc       = "https://${azurerm_container_app.main.latest_revision_fqdn}/redoc"
    api_tickets = "https://${azurerm_container_app.main.latest_revision_fqdn}/api/v1/tickets"
  }
}


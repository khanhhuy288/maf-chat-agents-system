#!/bin/bash
# Deployment script for Azure Container Apps
# Ensures correct order: Infrastructure → Build Image → Container App

set -e  # Exit on error

echo "🚀 Starting deployment process..."
echo ""

# Check if we're in the terraform directory
if [ ! -f "main.tf" ]; then
    echo "❌ Error: This script must be run from the terraform directory"
    exit 1
fi

# Check if terraform is initialized
if [ ! -d ".terraform" ]; then
    echo "📦 Initializing Terraform..."
    terraform init
fi

# Stage 1: Create infrastructure (except Container App)
echo ""
echo "📋 Stage 1: Creating infrastructure (ACR, Key Vault, etc.)..."
echo "   (Skipping Container App - will be created after image is built)"
echo ""

terraform apply \
  -target=azurerm_resource_group.main \
  -target=azurerm_log_analytics_workspace.main \
  -target=azurerm_container_app_environment.main \
  -target=azurerm_container_registry.main \
  -target=azurerm_key_vault.main \
  -target=azurerm_key_vault_secret.azure_openai_api_key \
  -target=azurerm_key_vault_secret.ticket_logic_app_url \
  -target=azurerm_user_assigned_identity.container_app \
  -target=azurerm_role_assignment.acr_pull \
  -auto-approve

# Get ACR name
ACR_NAME=$(terraform output -raw container_registry_name)
echo ""
echo "✅ Infrastructure created!"
echo "   ACR Name: $ACR_NAME"
echo ""

# Stage 2: Build and push Docker image
echo "🐳 Stage 2: Building and pushing Docker image to ACR..."
echo ""

cd ..
az acr build --registry "$ACR_NAME" \
  --image ticket-api:latest \
  --file Dockerfile.api \
  .

echo ""
echo "✅ Docker image built and pushed!"
echo ""

# Stage 3: Create Container App
echo "📦 Stage 3: Creating Container App..."
echo "   (Image now exists, Container App can pull it successfully)"
echo ""

cd terraform
terraform apply \
  -target=azurerm_container_app.main \
  -target=azurerm_key_vault_access_policy.container_app \
  -auto-approve

echo ""
echo "🎉 Deployment complete!"
echo ""
echo "📊 Container App URL:"
terraform output container_app_url
echo ""
echo "🔗 API Endpoints:"
terraform output api_endpoints
echo ""
echo "📝 View logs:"
echo "   $(terraform output -raw view_logs_command)"


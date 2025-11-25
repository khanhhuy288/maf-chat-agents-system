# Terraform Infrastructure for Azure Container Apps

This directory contains Terraform configuration for deploying the Chat Agents System to Azure Container Apps.

## Quick Start

1. **Copy and configure variables:**
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   # Edit terraform.tfvars with your values
   ```

2. **Initialize Terraform:**
   ```bash
   terraform init
   ```

3. **Review the plan:**
   ```bash
   terraform plan
   ```

4. **Deploy:**
   ```bash
   terraform apply
   ```

5. **Build and push Docker image:**
   ```bash
   ACR_NAME=$(terraform output -raw container_registry_name)
   az acr build --registry $ACR_NAME \
     --image ticket-api:latest \
     --file ../Dockerfile.api \
     ..
   ```

## Files

- `main.tf` - Main infrastructure configuration
- `variables.tf` - Variable definitions
- `outputs.tf` - Output values
- `terraform.tfvars.example` - Example configuration (copy to `terraform.tfvars`)

## Documentation

For detailed instructions, see [TERRAFORM_GUIDE.md](../TERRAFORM_GUIDE.md) in the project root.

## Important Notes

- **Never commit `terraform.tfvars`** - it contains sensitive data
- **State files are gitignored** - use remote state backend for team collaboration
- **Key Vault secrets** - The Container App uses managed identity to access Key Vault secrets at runtime


# Azure Container Apps Deployment

Short guide to deploy the Chat Agents API to Azure Container Apps with Terraform.

## Table of Contents
- [Essentials](#1-essentials)
- [Terraform Layout & Variables](#2-terraform-layout--variables)
- [Deployment Workflow](#3-deployment-workflow)
- [Updating After Launch](#4-updating-after-launch)
- [Environment Strategy](#5-environment-strategy)
- [CI/CD Snapshot](#6-cicd-snapshot)
- [Secrets & Key Vault](#7-secrets--key-vault)
- [Scaling, Cost, Monitoring](#8-scaling-cost-monitoring)
- [Troubleshooting Quick Hits](#9-troubleshooting-quick-hits)
- [Terraform Command Cheat Sheet](#10-terraform-command-cheat-sheet)
- [API Surface After Deploy](#11-api-surface-after-deploy)
- [Next Steps & References](#12-next-steps--references)

---

## 1. Essentials
- Tools: Terraform ≥ 1.0, Azure CLI ≥ 2.0, Docker (`brew install terraform azure-cli docker` on macOS)
- Azure assets needed: subscription + rights for Resource Group, Container Apps Environment, Container Registry, Key Vault, Log Analytics, optional App Insights
- Secrets: Azure OpenAI endpoint + API key, Logic App webhook URL
- Login flow: `az login && az account set --subscription "<name-or-id>"`

---

## 2. Terraform Layout & Variables

```
terraform/
├─ main.tf        # resources
├─ variables.tf   # inputs
├─ outputs.tf     # urls/commands
└─ terraform.tfvars.example
```

1. `cd terraform`
2. `cp terraform.tfvars.example terraform.tfvars`
3. Fill at minimum:

```hcl
project_name          = "ticket-api"
location              = "westeurope"
resource_group_name   = "ticket-rg"
azure_openai_endpoint = "https://<resource>.openai.azure.com/"
azure_openai_api_key  = "..."
ticket_logic_app_url  = "https://<logic-app>/api/..."
```

Optional knobs: `min_replicas`, `max_replicas`, CPU/memory, `enable_application_insights`, `tags`.

> `terraform.tfvars` stays local. For teams, enable the Azure Storage backend block in `main.tf` so state lives in one place.

## 3. Deployment Workflow
> Container Apps pulls the image immediately. Always build/push before creating the app.

Use `@terraform/deploy.sh` (run it from within the `terraform/` directory) so the order stays correct: infrastructure ➜ image ➜ Container App. The script runs `terraform init/plan` as needed, waits for the ACR image build to finish, and only then creates the Container App.

Already have an image in ACR? Run a single `terraform apply` after `plan`.

## 4. Updating After Launch
- **Infra change**: edit `.tf` → `terraform plan` → `terraform apply`.
- **App-only change**:

```bash
ACR_NAME=$(terraform output -raw container_registry_name)
az acr build --registry $ACR_NAME \
  --image ticket-api:${GITHUB_SHA:-latest} \
  --file Dockerfile.api \
  .

az containerapp update \
  --name $(terraform output -raw container_app_name) \
  --resource-group $(terraform output -raw resource_group_name) \
  --image "$ACR_NAME.azurecr.io/ticket-api:${GITHUB_SHA:-latest}"
```

Use tags like `dev-latest`, `staging-<sha>`, `prod-<semver>`.

## 5. Environment Strategy
- Separate resource groups per env (`rg-chat-agents-{dev,staging,prod}`)
- One tfvars per env (`terraform.dev.tfvars`, etc.) + matching GitHub secrets
- Single ACR with env-specific tags unless stricter isolation requires multiple registries
- Per-env Key Vaults for secret isolation
- Terraform state in Azure Storage with key `container-apps-<env>.tfstate`

---

## 6. CI/CD Snapshot
1. Push to `develop` deploys to dev (automatic after tests).
2. Merge to `staging` promotes to staging (run integration tests + smoke checks).
3. Merge to `main` deploys to prod (requires manual approval + monitoring window).
4. Each stage runs the same steps: checkout → tests → Terraform plan/apply with env tfvars → `az acr build` → `az containerapp update` → health probe (`/health`).
5. Tag container images per environment (`dev-latest`, `staging-<sha>`, `prod-<semver>`) to keep rollbacks simple.

## 7. Secrets & Key Vault
- Terraform provisions Key Vault, stores Azure OpenAI key + Logic App URL, then injects them as env vars
- Updating secrets requires updating `terraform.tfvars` (or KV) + `terraform apply`
- Useful commands:

```bash
KV_NAME=$(terraform output -raw key_vault_name)
az keyvault secret list --vault-name $KV_NAME
az keyvault secret show --vault-name $KV_NAME --name azure-openai-api-key -o tsv
```

## 8. Scaling, Cost, Monitoring
- Set `min_replicas`/`max_replicas` per env (`min_replicas=0` for dev to scale to zero)
- Reduce CPU/memory + log retention outside prod
- Enable App Insights via `enable_application_insights = true`, then use `terraform output application_insights_connection_string`
- Logs:

```bash
az containerapp logs show \
  --name $(terraform output -raw container_app_name) \
  --resource-group $(terraform output -raw resource_group_name) \
  --tail 100
```

## 9. Troubleshooting Quick Hits
- Auth: `az login` + `az account set`
- Name collisions: adjust `project_name`
- Image pull errors: ensure role assignment on ACR for managed identity (`az role assignment list ...`)
- App stuck starting: `az containerapp show ... --query properties.runningStatus`
- Health: `curl $(terraform output -raw container_app_url)/health`

---

## 10. Terraform Command Cheat Sheet
```bash
terraform init
terraform plan
terraform apply
terraform fmt
terraform validate
terraform output
terraform destroy   # irreversible
```

## 11. API Surface After Deploy
- `GET /health`, `GET /ready`
- `GET /docs`, `GET /redoc`
- `POST /api/v1/tickets` (primary workflow endpoint)

---

## 12. Next Steps & References
- Wire GitHub Actions secrets per environment
- Turn on remote state + App Insights dashboards
- Add custom domain via `azurerm_container_app_custom_domain`
- References: Azure Container Apps docs, Terraform AzureRM provider docs

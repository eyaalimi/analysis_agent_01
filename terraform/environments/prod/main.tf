# terraform/environments/prod/main.tf
# PROD environment — calls the root Terraform module with production-specific values.
#
# Usage:
#   cd terraform/environments/prod
#   terraform init
#   terraform plan -var-file="terraform.tfvars"
#   terraform apply -var-file="terraform.tfvars"
#
# WARNING: This environment affects real users. Always review the plan before applying.

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Uncomment after creating the S3 bucket and DynamoDB table (see terraform/backend.tf)
  # backend "s3" {
  #   bucket         = "procurement-ai-tfstate"
  #   key            = "prod/terraform.tfstate"
  #   region         = "us-east-1"
  #   encrypt        = true
  #   dynamodb_table = "procurement-ai-tfstate-lock"
  # }
}

# ── Call root module with PROD-specific values ────────────────────────────────
module "procurement_agent" {
  source = "../../"

  project_name         = "procurement-agent-prod"
  aws_region           = var.aws_region
  image_tag            = var.image_tag
  bedrock_model_id     = var.bedrock_model_id
  ses_recipient_emails = var.ses_recipient_emails
  gmail_address        = var.gmail_address
  gmail_app_password   = var.gmail_app_password
  database_url         = var.database_url
  log_level            = "INFO"

  tags = {
    Project     = "procurement-ai"
    Environment = "prod"
    ManagedBy   = "terraform"
  }
}

# ── Variables (override values in terraform.tfvars) ───────────────────────────
variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "image_tag" {
  description = "Docker image tag to deploy (use a specific git SHA in prod, not 'latest')"
  type        = string
  default     = "latest"
}

variable "bedrock_model_id" {
  description = "AWS Bedrock model ID"
  type        = string
  default     = "us.anthropic.claude-sonnet-4-20250514-v1:0"
}

variable "ses_recipient_emails" {
  description = "Email addresses SES should accept (must be on a verified domain)"
  type        = list(string)
  default     = []
}

variable "gmail_address" {
  description = "Gmail address for sending ACK emails"
  type        = string
  sensitive   = true
  default     = ""
}

variable "gmail_app_password" {
  description = "Gmail App Password for SMTP auth"
  type        = string
  sensitive   = true
  default     = ""
}

variable "database_url" {
  description = "PostgreSQL connection URL (optional)"
  type        = string
  sensitive   = true
  default     = ""
}

# ── Pass-through outputs ───────────────────────────────────────────────────────
output "ecr_repository_url" {
  description = "ECR repository URL"
  value       = module.procurement_agent.ecr_repository_url
}

output "s3_bucket_name" {
  description = "S3 bucket name"
  value       = module.procurement_agent.s3_bucket_name
}

output "lambda_function_name" {
  description = "Lambda function name"
  value       = module.procurement_agent.lambda_function_name
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group"
  value       = module.procurement_agent.cloudwatch_log_group
}

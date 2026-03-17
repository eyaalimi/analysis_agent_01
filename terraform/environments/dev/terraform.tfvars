# terraform/environments/dev/terraform.tfvars
# Development environment variable values.
# Copy this file and fill in real values before running terraform apply.
# Do NOT commit real secrets — use AWS Secrets Manager or GitHub Secrets in CI/CD.

aws_region           = "us-east-1"
image_tag            = "latest"
bedrock_model_id     = "us.anthropic.claude-sonnet-4-20250514-v1:0"
ses_recipient_emails = []    # e.g. ["dev-procurement@yourdomain.com"]
gmail_address        = ""    # e.g. "your-gmail@gmail.com"
gmail_app_password   = ""    # e.g. "xxxx xxxx xxxx xxxx"
database_url         = ""    # e.g. "postgresql://user:pass@host:5432/db"

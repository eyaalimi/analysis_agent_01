# terraform/environments/prod/terraform.tfvars
# Production environment variable values.
# Do NOT commit real secrets — use AWS Secrets Manager or GitHub Secrets in CI/CD.

aws_region           = "us-east-1"
image_tag            = "latest"    # Use a specific git SHA in production (e.g. "a1b2c3d")
bedrock_model_id     = "us.anthropic.claude-sonnet-4-20250514-v1:0"
ses_recipient_emails = []    # e.g. ["procurement@yourdomain.com"]
gmail_address        = ""    # e.g. "your-gmail@gmail.com"
gmail_app_password   = ""    # e.g. "xxxx xxxx xxxx xxxx"
database_url         = ""    # e.g. "postgresql://user:pass@rds-host:5432/db"

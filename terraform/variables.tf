variable "aws_region" {
  description = "AWS region to deploy to"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Name prefix for all resources (e.g. 'procurement-agent')"
  type        = string
  default     = "procurement-agent"
}

variable "image_tag" {
  description = "Docker image tag to deploy (e.g. 'latest' or a git SHA)"
  type        = string
  default     = "latest"
}

variable "bedrock_model_id" {
  description = "AWS Bedrock model ID for Claude"
  type        = string
  default     = "us.anthropic.claude-sonnet-4-20250514-v1:0"
}

variable "ses_recipient_emails" {
  description = "List of email addresses that SES should process (must be on a verified SES domain)"
  type        = list(string)
  # Example: ["procurement@yourdomain.com"]
}

variable "gmail_address" {
  description = "Gmail address used to send ACK emails via SMTP"
  type        = string
  sensitive   = true
}

variable "gmail_app_password" {
  description = "Gmail App Password (16-char, no spaces) for SMTP auth"
  type        = string
  sensitive   = true
}

variable "database_url" {
  description = "Optional PostgreSQL connection URL (leave empty if not using a DB)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "log_level" {
  description = "Python log level (DEBUG, INFO, WARNING, ERROR)"
  type        = string
  default     = "INFO"
}

variable "tags" {
  description = "Tags applied to all AWS resources"
  type        = map(string)
  default = {
    Project     = "procurement-agent"
    Environment = "production"
    ManagedBy   = "terraform"
  }
}

# terraform/backend.tf
# Remote state configuration using S3 + DynamoDB locking.
#
# SETUP STEPS (one-time, before first `terraform init`):
#   1. Create the S3 bucket manually:
#      aws s3api create-bucket --bucket procurement-ai-tfstate --region us-east-1
#      aws s3api put-bucket-versioning --bucket procurement-ai-tfstate \
#        --versioning-configuration Status=Enabled
#
#   2. Create the DynamoDB table for state locking:
#      aws dynamodb create-table \
#        --table-name procurement-ai-tfstate-lock \
#        --attribute-definitions AttributeName=LockID,AttributeType=S \
#        --key-schema AttributeName=LockID,KeyType=HASH \
#        --billing-mode PAY_PER_REQUEST
#
#   3. Uncomment the backend block below and run `terraform init`.
#
# NOTE: While developing locally, you can keep this commented out.
#       The state will be stored in terraform.tfstate (local file).

# terraform {
#   backend "s3" {
#     bucket         = "procurement-ai-tfstate"
#     key            = "root/terraform.tfstate"
#     region         = "us-east-1"
#     encrypt        = true
#     dynamodb_table = "procurement-ai-tfstate-lock"
#   }
# }

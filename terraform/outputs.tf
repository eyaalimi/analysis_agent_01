output "ecr_repository_url" {
  description = "ECR repository URL — use this to tag and push your Docker image"
  value       = aws_ecr_repository.agent.repository_url
}

output "s3_bucket_name" {
  description = "S3 bucket name for emails and results"
  value       = aws_s3_bucket.emails.bucket
}

output "lambda_function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.agent.function_name
}

output "lambda_function_arn" {
  description = "Lambda function ARN"
  value       = aws_lambda_function.agent.arn
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group for Lambda logs"
  value       = aws_cloudwatch_log_group.agent.name
}

output "ses_rule_set_name" {
  description = "SES receipt rule set name"
  value       = aws_ses_receipt_rule_set.main.rule_set_name
}

output "push_image_commands" {
  description = "Commands to build and push the Docker image to ECR"
  value = <<-EOT
    # 1. Authenticate Docker to ECR
    aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${aws_ecr_repository.agent.repository_url}

    # 2. Build the image (run from project root)
    docker build --platform linux/amd64 -t ${var.project_name} .

    # 3. Tag and push
    docker tag ${var.project_name}:latest ${aws_ecr_repository.agent.repository_url}:latest
    docker push ${aws_ecr_repository.agent.repository_url}:latest

    # 4. Update Lambda to use the new image
    aws lambda update-function-code \
      --function-name ${aws_lambda_function.agent.function_name} \
      --image-uri ${aws_ecr_repository.agent.repository_url}:latest
  EOT
}

# 상태는 S3 에 둔다 (infra/terraform-bootstrap 이 만든 버킷·잠금 테이블).
# 버전 관리·암호화가 켜져 있고, apply 중에는 DynamoDB 가 잠가서 동시에 못 건드린다.
# 옮긴 순서는 backend.tf.example 에 있다.
terraform {
  backend "s3" {
    bucket         = "stockcast-tfstate-049413008851"
    key            = "stockcast/terraform.tfstate"
    region         = "ap-northeast-2"
    dynamodb_table = "stockcast-tflock"
    encrypt        = true
  }
}

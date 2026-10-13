terraform {
  required_version = "= 1.15.8"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.21.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "= 2.8.1"
    }
  }
}

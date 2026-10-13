terraform {
  required_version = "= 1.15.8"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.21.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "= 3.3.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "= 3.3.0"
    }
  }
  backend "s3" {}
}

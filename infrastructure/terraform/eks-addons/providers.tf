data "terraform_remote_state" "eks" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = var.eks_state_key
    region = var.aws_region
  }
}

locals {
  eks = data.terraform_remote_state.eks.outputs
  # Short-lived tokens from the AWS CLI so long helm waits never outlive a static token.
  kube_exec = {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--region", var.aws_region, "--cluster-name", local.eks.cluster_name, "--output", "json"]
  }
}

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.expected_account_id]
  default_tags {
    tags = {
      Project   = "aws-devops-practical-assessment"
      Component = "eks-addons"
      ManagedBy = "Terraform"
    }
  }
}

provider "kubernetes" {
  host                   = local.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(local.eks.cluster_certificate_authority_data)
  exec {
    api_version = local.kube_exec.api_version
    command     = local.kube_exec.command
    args        = local.kube_exec.args
  }
}

provider "helm" {
  kubernetes = {
    host                   = local.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(local.eks.cluster_certificate_authority_data)
    exec                   = local.kube_exec
  }
}

data "terraform_remote_state" "ec2" {
  backend = "s3"

  config = {
    bucket = var.state_bucket
    key    = var.ec2_state_key
    region = var.aws_region
  }
}

resource "aws_route53_record" "ec2_app" {
  zone_id = aws_route53_zone.assessment.zone_id
  name    = "${var.app_record_name}.${var.domain_name}"
  type    = "A"

  alias {
    name                   = data.terraform_remote_state.ec2.outputs.alb_dns_name
    zone_id                = data.terraform_remote_state.ec2.outputs.alb_zone_id
    evaluate_target_health = true
  }
}

output "ec2_app_url" {
  value = "http://${aws_route53_record.ec2_app.fqdn}"
}

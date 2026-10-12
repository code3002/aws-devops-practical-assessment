data "aws_lbs" "ec2_app" {
  tags = {
    Name = "aws-devops-assessment-ec2-01-app"
  }
}

data "aws_lb" "ec2_app" {
  arn = one(data.aws_lbs.ec2_app.arns)
}

resource "aws_route53_record" "ec2_app" {
  zone_id = aws_route53_zone.assessment.zone_id
  name    = "app.aws.rahulbagal.tech"
  type    = "A"

  alias {
    name                   = data.aws_lb.ec2_app.dns_name
    zone_id                = data.aws_lb.ec2_app.zone_id
    evaluate_target_health = true
  }
}

output "ec2_app_url" {
  value = "http://${aws_route53_record.ec2_app.fqdn}"
}

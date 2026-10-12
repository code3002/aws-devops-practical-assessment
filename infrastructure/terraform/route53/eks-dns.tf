resource "aws_route53_record" "eks_app" {
  zone_id = aws_route53_zone.assessment.zone_id
  name    = "eks.aws.rahulbagal.tech"
  type    = "A"

  alias {
    name                   = "k8s-pythonti-pythonti-c017190bfa-1568225166.ap-south-1.elb.amazonaws.com"
    zone_id                = "ZP97RAFLXTNZK"
    evaluate_target_health = false
  }
}

output "eks_app_url" {
  value = "http://${aws_route53_record.eks_app.fqdn}"
}

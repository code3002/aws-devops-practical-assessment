output "cluster_name" { value = local.eks.cluster_name }
output "gateway_alb_dns_name" { value = data.kubernetes_resource.gateway.object.status.addresses[0].value }
output "eks_app_url" { value = "http://${aws_route53_record.eks_app.fqdn}" }
output "python_image" { value = local.python_image }
output "kafka_verify_command" { value = "bash infrastructure/kubernetes/kafka/verify-roundtrip.sh" }

resource "aws_lb" "app" {
  depends_on                 = [aws_internet_gateway.this]
  internal                   = false
  load_balancer_type         = "application"
  ip_address_type            = "ipv4"
  subnets                    = [aws_subnet.this["public_a"].id, aws_subnet.this["public_b"].id]
  security_groups            = [aws_security_group.alb.id]
  enable_deletion_protection = false
  tags                       = { Name = "${var.deployment_id}-app" }
}
resource "aws_lb_target_group" "app" {
  port        = 80
  protocol    = "HTTP"
  target_type = "instance"
  vpc_id      = aws_vpc.this.id
  health_check {
    path     = "/health"
    protocol = "HTTP"
    port     = "traffic-port"
    matcher  = "200"
  }
}
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}
resource "aws_lb_target_group_attachment" "app" {
  target_group_arn = aws_lb_target_group.app.arn
  target_id        = aws_instance.app.id
  port             = 80
}

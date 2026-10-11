resource "aws_db_subnet_group" "app" {
  name       = "${var.deployment_id}-database"
  subnet_ids = [aws_subnet.this["database_a"].id, aws_subnet.this["database_b"].id]
}
resource "aws_db_instance" "app" {
  identifier                  = "${var.deployment_id}-postgres"
  engine                      = "postgres"
  engine_version              = var.postgres_version
  instance_class              = "db.t4g.micro"
  db_name                     = "assessment"
  username                    = "assessment_admin"
  manage_master_user_password = true
  db_subnet_group_name        = aws_db_subnet_group.app.name
  availability_zone           = aws_subnet.this["database_a"].availability_zone
  vpc_security_group_ids      = [aws_security_group.rds.id]
  multi_az                    = false
  publicly_accessible         = false
  storage_encrypted           = true
  storage_type                = "gp3"
  allocated_storage           = 20
  max_allocated_storage       = 0
  auto_minor_version_upgrade  = false
  engine_lifecycle_support    = "open-source-rds-extended-support-disabled"
  # Disposable data: teardown leaves no snapshots or retained backups.
  deletion_protection      = false
  skip_final_snapshot      = true
  backup_retention_period  = 0
  delete_automated_backups = true
}

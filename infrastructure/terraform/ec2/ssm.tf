locals {
  tool_files      = ["scripts/deploy/prepare.py", "scripts/deploy/deploy.sh", "scripts/deploy/artifact.py", "scripts/database/configure.py", "scripts/database/initialize.cjs", "scripts/database/initialize.sql"]
  tools_sha256    = sha256(jsonencode({ for name in local.tool_files : name => filesha256("${path.module}/../../../${name}") }))
  tools_directory = "/opt/assessment/tools/${local.tools_sha256}"
  install_tools = concat([
    "set -eu; umask 077",
    "cloud-init status --wait >/dev/null",
    "test -d /opt/assessment && test ! -L /opt/assessment",
    "for dir in /opt/assessment /opt/assessment/tools ${local.tools_directory}; do if test -e \"$dir\" || test -L \"$dir\"; then test -d \"$dir\" && test ! -L \"$dir\" && test \"$(stat -c %u \"$dir\")\" = 0 && test \"$(( 0$(stat -c %a \"$dir\") & 022 ))\" = 0; fi; done",
    "install -d -o root -g root -m 0750 /opt/assessment/tools ${local.tools_directory}",
    "work=$(mktemp -d /opt/assessment/.tools.XXXXXX); trap 'rm -rf -- \"$work\"' EXIT"
    ], flatten([for name in local.tool_files : [
      "printf '%s' '${filebase64("${path.module}/../../../${name}")}' | base64 --decode > \"$work/file\"",
      "printf '%s  %s\\n' '${filesha256("${path.module}/../../../${name}")}' \"$work/file\" | sha256sum --check --status",
      "install -d -o root -g root -m 0750 ${local.tools_directory}/${dirname(trimprefix(name, "scripts/"))}",
      "install -o root -g root -m 0640 \"$work/file\" ${local.tools_directory}/${trimprefix(name, "scripts/")}"
    ]]), [
    "printf '%s' '{{ Configuration }}' | base64 --decode > \"$work/config.json\"",
    "python3 ${local.tools_directory}/deploy/prepare.py \"$work/config.json\""
  ])
}
resource "aws_ssm_document" "deploy" {
  name            = var.ssm_document_name != null ? var.ssm_document_name : "${var.deployment_id}-app-deploy"
  document_type   = "Command"
  document_format = "JSON"
  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Versioned trusted helpers; identifiers only; initial setup or subsequent deployment"
    parameters    = { Configuration = { type = "String", description = "Base64 JSON of reviewed nonsecret identifiers", allowedPattern = "^[A-Za-z0-9+/=]+$" } }
    mainSteps     = [{ action = "aws:runShellScript", name = "Deploy", inputs = { timeoutSeconds = "1800", runCommand = local.install_tools } }]
  })
}

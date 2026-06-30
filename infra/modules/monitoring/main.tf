# Observability stack — kube-prometheus-stack (Prometheus + Alertmanager + Grafana +
# node-exporter + kube-state-metrics). Phase-2 (Helm cần EKS thật + helm provider).
#
# Luồng telemetry-contract §2.5.C: Prometheus alert (PrometheusRule) → Alertmanager
# → webhook Alert Forwarder (ns monitoring) → SQS → Executor.
# Grafana: dashboards cluster-health / OOM / restarts (datasource Prometheus).

resource "helm_release" "kube_prometheus_stack" {
  name             = "kube-prometheus-stack"
  repository       = "https://prometheus-community.github.io/helm-charts"
  chart            = "kube-prometheus-stack"
  namespace        = "monitoring"
  create_namespace = true
  version          = "65.1.1"

  values = [yamlencode({
    grafana = {
      adminPassword = var.grafana_admin_password
      service       = { type = "ClusterIP" } # không expose public, access qua port-forward
      sidecar = {
        dashboards = { enabled = true, label = "grafana_dashboard" }
      }
    }

    prometheus = {
      prometheusSpec = {
        retention = "7d"
        # Cho phép Prometheus nhặt ServiceMonitor/PodMonitor/PrometheusRule ở MỌI namespace
        # (mặc định chart chỉ nhặt cái có label release của chart).
        serviceMonitorSelectorNilUsesHelmValues = false
        podMonitorSelectorNilUsesHelmValues     = false
        ruleSelectorNilUsesHelmValues           = false
        probeSelectorNilUsesHelmValues          = false
      }
    }

    # Route mọi alert đang firing → Alert Forwarder webhook → SQS.
    # LƯU Ý: phải có receiver "null" + routes=[] vì chart kube-prometheus-stack mặc định
    # có child-route trỏ receiver "null" (Watchdog/InhibitInfo); nếu thiếu → operator báo
    # "undefined receiver null used in route" và KHÔNG tạo được Alertmanager.
    alertmanager = {
      config = {
        route = {
          receiver        = "cdo-forwarder"
          routes          = []
          group_by        = ["namespace", "alertname"]
          group_wait      = "10s"
          group_interval  = "30s"
          repeat_interval = "5m"
        }
        receivers = [
          { name = "null" },
          {
            name = "cdo-forwarder"
            webhook_configs = [{
              url           = var.forwarder_webhook_url
              send_resolved = true
            }]
          },
        ]
      }
    }
  })]
}

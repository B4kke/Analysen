FROM searxng/searxng:2026.9.17-274b63b67@sha256:ba0a344c566ecc6e4429e81d02d93a01fa05c80e9fb6d08f0a1e57a729aa6d87

# Ship versioned configuration without depending on host filesystem mounts.
COPY config/searxng/settings.yml /etc/searxng/settings.yml

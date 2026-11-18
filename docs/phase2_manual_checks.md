# Lệnh kiểm thử Deployment Phase 2 (Chạy trên Terminal)

**1. SEC-05 & DEP-03: Kiểm tra LAN & Keycloak Admin (Từ máy Client thứ 2 trong mạng LAN)**
```bash
# Phải trả về 403 hoặc 404 (Caddy chặn admin)
curl -k -I https://<IP_SERVER>/auth/admin

# Kiểm tra PostgreSQL không bị lộ port ra LAN (Nên báo Connection refused)
nc -zv <IP_SERVER> 5432
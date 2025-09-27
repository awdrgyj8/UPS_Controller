from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

# 產生一組 Ed25519 金鑰
private_key = ed25519.Ed25519PrivateKey.generate()
public_key = private_key.public_key()

# 存檔（私鑰要安全保管）
# 私只留本機 公放在節點
with open("../Keys/private_key.pem", "wb") as f:
    f.write(private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))

with open("../Keys/public_key.pem", "wb") as f:
    f.write(public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ))

print("生成完成：controller_private_key.pem & controller_public_key.pem")

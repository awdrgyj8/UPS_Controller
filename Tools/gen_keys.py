from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

CONTROLLER_DIR = Path(__file__).resolve().parents[1]
KEYS_DIR = CONTROLLER_DIR / "Keys"
PRIVATE_KEY_PATH = KEYS_DIR / "private_key.pem"
PUBLIC_KEY_PATH = KEYS_DIR / "public_key.pem"
AGENT_DIR = CONTROLLER_DIR.parent / "UPS_Agent"
AGENT_PUBLIC_KEY_PATH = AGENT_DIR / "Key" / "public_key.pem"

# 產生一組 Ed25519 金鑰
private_key = ed25519.Ed25519PrivateKey.generate()
public_key = private_key.public_key()

# 存檔（私鑰要安全保管）
# 私只留本機 公放在節點
KEYS_DIR.mkdir(parents=True, exist_ok=True)

with open(PRIVATE_KEY_PATH, "wb") as f:
    f.write(private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))

with open(PUBLIC_KEY_PATH, "wb") as f:
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    f.write(public_key_bytes)

if AGENT_DIR.exists():
    AGENT_PUBLIC_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(AGENT_PUBLIC_KEY_PATH, "wb") as f:
        f.write(public_key_bytes)

print(f"生成完成：{PRIVATE_KEY_PATH}")
print(f"生成完成：{PUBLIC_KEY_PATH}")
if AGENT_DIR.exists():
    print(f"生成完成：{AGENT_PUBLIC_KEY_PATH}")

import bcrypt

password = "mzej3s23ar"  # 您想要嘅密碼
hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
print(hashed.decode('utf-8'))  # 輸出加密後嘅密碼
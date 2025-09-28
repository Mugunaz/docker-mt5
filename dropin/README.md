# Quick-Start

1. add instance to docker compose
2. Create directory:

```
mkdir -p instances/mt5-#
sudo chown -R 1000:1000 instances/mt5-#
chmod -R u+rwX,g+rwX instances/mt5-#
```

3. Spin up Container
4. Run Commands:

```
docker exec -it -u 0 mt5-# bash
```

```
echo "kasm-user ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/99-kasm-user
chmod 440 /etc/sudoers.d/99-kasm-user
```

5. Download MT5 and Python
```
 wget https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5linux.sh ; chmod +x mt5linux.sh ; ./mt5linux.sh 

```

# VM Login

Username: kasm_user
Password: set in .env
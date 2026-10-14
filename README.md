cd fba-demo
docker compose down -v
cd ..
rmdir /s /q fba-demo
python fba_docker_demo.py --nodes 6
cd fba-demo
docker compose up -d
python fba_dashboard.py
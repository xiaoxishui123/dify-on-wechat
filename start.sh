ps -ef | grep app.py | grep -v grep | awk '{print $2}' | xargs kill
nohup python3.9  -u app.py >> wechat_robot.log 2>&1 &


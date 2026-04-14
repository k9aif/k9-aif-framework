## steps to setup environment



1. create folder "ai"
2. cd to "ai'
3. git clone https://github.com/k9aif/k9-aif-framework.git
4. cd k9-aif-framework
5. python3 -m venv .venv
6. source .venv/bin/activate
7. Now, you should be in the prompt with the prefix (.venv)
8. pip install -r requirements.txt

9. ## Now, the environment is ready

Do your first test

ensure the config.yaml in the folder examples/k9chat/config.yaml points to your LLM 
then, run the below command

./run_k9chat.sh (assuming you are on a Unix/Linux machine) 

This should launch the k9chat and then it should run flawlessly.

``` bash
(.venv) ravinata@raspberrypi:~/k9-aif-framework $ ./run_k9chat.sh
INFO:     Will watch for changes in these directories: ['/home/ravinata/k9-aif-framework']
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [22071] using WatchFiles
INFO:     Started server process [22087]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     127.0.0.1:39220 - "GET / HTTP/1.1" 200 OK
INFO:     127.0.0.1:39220 - "GET /static/style.css HTTP/1.1" 200 OK
INFO:     127.0.0.1:39220 - "GET /favicon.ico HTTP/1.1" 404 Not Found   (ignore this)

Open your browser and test out the chat.

Now, since this is working, you can then go to the folders and look at the code.

```




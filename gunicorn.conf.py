bind = "unix:/var/www/value-investing/value-investing.sock"
workers = 1
worker_class = "uvicorn.workers.UvicornWorker"
chdir = "/var/www/value-investing"
accesslog = "-"
errorlog = "-"

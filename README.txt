1. 将本目录的所有文件拷贝或者下载到目标机器的任意目录，目标机器一般是cobbler或者monitor（限12inN）
2. 执行bash install.sh
3. 进入目标机器的/home/codes/
4. 参考config.yml文件，配置需要同步的代码和配置，和需要重启的服务
5. 修改/home/codes/下的文件相关代码和配置目录
6. 执行code_sync，即可同步代码和配置，并重启相关服务
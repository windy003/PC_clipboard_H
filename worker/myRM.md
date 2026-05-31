

命令注册失败时,看这个


这是 Windows PowerShell 5.1
  一个著名的坑:它把参数传给原生程序(curl.exe)时,会把字符串里的双引号"吃掉",所以 curl 收到的 JSON   
  双引号没了,Worker 解析不出字段 → "不能为空"。单引号、\" 各种转义在 5.1 里都很难绕。

  最干净的办法:把 JSON 写进文件,让 curl 从文件读 body,彻底避开引号问题。两条命令:

  Set-Content -Path body.json -Value '{"username":"用户名","password":"密码"}' -Encoding ascii  
  -NoNewline
  curl.exe -X POST "https://clipboard-fav-worker.mybrowser.workers.dev/register" -H
  "X-Register-Secret: 这里填register_secret_key" -H "Content-Type: application/json"    
  --data "@body.json"

  - 第一条:把 JSON 存成 body.json(-Encoding ascii 避免 PowerShell 默认的 UTF-16 BOM 破坏内容)。    
  - 第二条:--data "@body.json" 让 curl 读这个文件当请求体。

  预期返回:

  {"ok":true}

  成功后可以把临时文件删掉:Remove-Item body.json。
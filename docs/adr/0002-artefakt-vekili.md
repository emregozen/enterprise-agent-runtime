# 0002. Artefaktlar kontrol düzleminden geçer

S3 anahtarı koşum poduna konmaz. Harness dosyayı kontrol düzleminin iç uç noktasına gönderir; düzlem yerel diske veya yapılandırılmış S3 uç noktasına yazar. Yirmi megabaytın üstü reddedilir.

Doğrudan poddan S3 daha az kopya demektir. Bu PoC’de kimlik bilgisinin poddan çıkmaması daha önemli.

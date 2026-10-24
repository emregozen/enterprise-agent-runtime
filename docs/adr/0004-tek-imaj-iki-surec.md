# 0004. Tek Python imajı, iki kap

Kontrol düzlemi ve koşum imajı aynıdır. Podda harness ve executor aynı imajdan iki kap olarak kalkar. Executor ortamında gizli değişken yoktur; çocuk süreç `python -I` ile temiz bir ortamda çalışır.

Yerelde Kubernetes yoksa aynı ayrım iki alt süreçle kurulur. Bu, OpenShift Job’unun yerine geçmez; API’nin ürettiği Secret ve Job belgeleri sahte Kubernetes istemcisine karşı test edilir.

Paylaşılan emptyDir ve aynı ağ ad alanı bilinçli bir sınırdır. Executor localhost’tan konuşur, dışarı kimlik taşımaz, yine de pod ağını görür.

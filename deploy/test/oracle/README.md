# Oracle Free denemesi

CRC üzerinde geçici Oracle Database Free 23 içindir. Üretim kurulumuna eklenmez. `anyuid` yalnız bu ad alanındaki `oracle` ServiceAccount’una verilir. PVC yoktur; pod silinince veri gider. Deneme bitince ölçekleyin:

```bash
oc -n oracle-test scale deploy/oracle-free --replicas=0
```

Adımlar, Secret’ın dosyadan nasıl üretileceği ve disk dolunca imaj budama notu `OPENSHIFT-LOCAL-CHECKLIST.md` bölüm 3 ve 9’dadır. Parola değerini bu dizine koymayın. `load-sales.sql` depoda yoktur; satır yükü gerekiyorsa `reload.sh` ile aynı dizine koyun, betik varsa onu çalıştırır.

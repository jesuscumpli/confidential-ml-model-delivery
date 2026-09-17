

# 1. Local Deployment (Roberta)

```bash
./scripts/gen-key.sh               
./scripts/gen-signing-keypair.sh
```

### Producer -> Publish

```bash
export HF_TOKEN=TO_COMPLETE
uv run producer run --key-path ./var/secrets/model.key \
  --signing-key-path ./var/secrets/signing.key \
  --repo-id jesuscumpli/confidential-ml-model --private \
  --mode chunked --model-id="FacebookAI/xlm-roberta-base" --artifact-name=roberta.enc \
  --metrics
```

Console output:
```text
Effective configuration
 model        FacebookAI/xlm-roberta-base@main            
 hub repo     jesuscumpli/confidential-ml-model (private) 
 hf token     set                                         
 cipher       aes-256-gcm                                 
 mode         chunked                                     
 chunk size   1,048,576 bytes                             
 metrics      on                                          
 key file     var/secrets/model.key                       
 signing      ed25519                                     
 signing key  var/secrets/signing.key                     
 artifact     var/artifacts/upload/roberta.enc            
 signature    var/artifacts/upload/roberta.sig            
 work dir     var/artifacts                               
INFO downloading FacebookAI/xlm-roberta-base@main
Fetching 5 files: 100%|██████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 5/5 [00:38<00:00,  7.74s/it]
Download complete: : ██████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 1.50GB, 17.4MB/s  INFO packaged 4 files (1124679680 bytes) at var/artifacts/model.tar████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 2.24GB / 2.24GB, 72.9MB/s  
INFO encrypted var/artifacts/model.tar -> var/artifacts/upload/roberta.enc (aes-256-gcm, chunked) in 0.85s (1261.3 MiB/s, peak RSS 1968.2 MiB)
INFO signed var/artifacts/upload/roberta.enc -> var/artifacts/upload/roberta.sig (ed25519)
Processing Files (1 / 1)      : 100%|█████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 1.12GB / 1.12GB, 29.6MB/s  
New Data Upload               : 100%|█████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 1.12GB / 1.12GB, 29.6MB/s  
  ...ifacts/upload/roberta.enc: 100%|█████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 1.12GB / 1.12GB            
INFO published roberta.enc, roberta.sig to jesuscumpli/confidential-ml-model (commit 2aca47e70ce28b1a7125447dbb00d799ac5eb1b7)
published roberta.enc + roberta.sig to jesuscumpli/confidential-ml-model at commit 2aca47e70ce28b1a7125447dbb00d799ac5eb1b7
Download complete: : ██████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 1.50GB, 17.4MB/s  
Reconstruction complete: 100%|████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 2.24GB / 2.24GB, 72.9MB/s
```

### Consumer -> Decrypt -> Inference

```bash
uv run consumer --key-path ./var/secrets/model.key \
  --public-key-path ./var/secrets/signing.pub \
  --repo-id jesuscumpli/confidential-ml-model --artifact-name=roberta.enc \
  --prompt="The capital of Spain is: <mask>." --metrics
```

```text
roberta.enc: downloading bytes: ███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 1.13GB, 31.4MB/s  
roberta.enc: reconstructing file: 100%|███████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 1.12GB / 1.12GB, 58.9MB/s  
INFO artifact roberta.enc (1124696866 bytes)
roberta.sig: 100%|█████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 106/106 [00:00<00:00, 942kB/s]
INFO signature roberta.sig verified (ed25519)
INFO decrypted artifact to plaintext package (1124679680 bytes, aes-256-gcm, chunked) in 0.62s (1740.4 MiB/s, peak RSS 695.4 MiB)
INFO restored FacebookAI/xlm-roberta-base@e73636d4f797dec63c3081bb6ed5c7b0bb3f2089 (4 files, manifest verified)
INFO model loaded: XLMRobertaForMaskedLM
prompt: The capital of Spain is: <mask>.
┏━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ # ┃ token     ┃ probability ┃
┡━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ 1 │ Madrid    │       0.455 │
│ 2 │ Barcelona │       0.339 │
│ 3 │ Valencia  │       0.022 │
│ 4 │ Bilbao    │       0.018 │
│ 5 │ Tarragona │       0.013 │
└───┴───────────┴─────────────┘
```

# 2. Docker + Kubernetes Deployment (Distilbert)

```bash
./scripts/kind-setup.sh
chmod 644 $PWD/var/secrets/*.key
```

### Docker: Producer -> Publish

```bash
docker run --rm -e HF_TOKEN -v "$PWD/var/secrets:/secrets:ro" producer:dev run \
  --model-id distilbert/distilbert-base-uncased --artifact-name distilbert.enc \
  --revision main --repo-id jesuscumpli/confidential-ml-model --private \
  --key-path /secrets/model.key --signing-key-path /secrets/signing.key \
  --mode chunked --metrics
```

Console output:

```text
Effective configuration
 model        distilbert/distilbert-base-uncased@main     
 hub repo     jesuscumpli/confidential-ml-model (private) 
 hf token     set                                         
 cipher       aes-256-gcm                                 
 mode         chunked                                     
 chunk size   1,048,576 bytes                             
 metrics      on                                          
 key file     /secrets/model.key                          
 signing      ed25519                                     
 signing key  /secrets/signing.key                        
 artifact     /work/artifacts/upload/distilbert.enc       
 signature    /work/artifacts/upload/distilbert.sig       
 work dir     /work/artifacts                             
INFO downloading distilbert/distilbert-base-uncased@main
Fetching 6 files: 100%|██████████| 6/6 [00:14<00:00,  2.50s/it]
INFO packaged 5 files (268666880 bytes) at /work/artifacts/model.tar
INFO encrypted /work/artifacts/model.tar -> /work/artifacts/upload/distilbert.enc (aes-256-gcm, chunked) in 0.15s (1742.9 MiB/s, peak RSS 455.4 MiB)
INFO signed /work/artifacts/upload/distilbert.enc -> /work/artifacts/upload/distilbert.sig (ed25519)
Processing Files (1 / 1)      : 100%|██████████|  269MB /  269MB, 8.57MB/s  
New Data Upload               : 100%|██████████|  269MB /  269MB, 8.57MB/s  
  ...cts/upload/distilbert.enc: 100%|██████████|  269MB /  269MB            
INFO published distilbert.enc, distilbert.sig to jesuscumpli/confidential-ml-model (commit 0d550165e3d08e9603ba758f4a6fca845b5db3f8)
published distilbert.enc + distilbert.sig to jesuscumpli/confidential-ml-model at commit 0d550165e3d08e9603ba758f4a6fca845b5db3f8
```

### Kubernetes Job: Consumer -> Decrypt -> Inference

```bash
alias k='kubectl --context kind-confidential-ml -n confidential-ml'
```

1. Secret: 

```bash
k create secret generic model-key --from-file=key=./var/secrets/model.key \
  --dry-run=client -o yaml | k apply -f -
```

2. Configmap: 

```bash
k create configmap consumer-config --from-literal=hub_repo_id=jesuscumpli/confidential-ml-model \
  --from-literal=artifact_name=distilbert.enc --from-literal=artifact_revision=main \
  --from-literal=prompt='El gato está sobre la [MASK].' --from-literal=top_k=3 \
  --dry-run=client -o yaml | k apply -f -
```

3. Configmap public sign:

```bash
PUBLIC_KEY_PATH=var/secrets/signing.pub NAMESPACE=confidential-ml scripts/gen-configmap-public-key.sh \
  k apply -f k8s/configmap-public-key.yaml
```
4. Job:

```bash
k delete job consumer --ignore-not-found --wait=true
k apply -f k8s/consumer-job.yaml
```

Help commands to debug:
```bash
k get pods -l app=consumer -w
k logs -f job/consumer
k get job consumer
```

Logs output:
```text
k logs -f job/consumer

INFO artifact distilbert.enc (268671010 bytes)
Warning: You are sending unauthenticated requests to the HF Hub. Please set a HF_TOKEN to enable higher rate limits and faster downloads.
WARNING Warning: You are sending unauthenticated requests to the HF Hub. Please set a HF_TOKEN to enable higher rate limits and faster downloads.
INFO signature distilbert.sig verified (ed25519)
INFO decrypted artifact to plaintext package (268666880 bytes, aes-256-gcm, chunked)
INFO restored distilbert/distilbert-base-uncased@12040accade4e8a0f71eabdb258fecc2e7e948be (5 files, manifest verified)
INFO model loaded: DistilBertForMaskedLM
prompt: El gato está sobre la [MASK].
┏━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ # ┃ token    ┃ probability ┃
┡━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ 1 │ vida     │       0.387 │
│ 2 │ isla     │       0.039 │
│ 3 │ historia │       0.039 │
└───┴──────────┴─────────────┘
```

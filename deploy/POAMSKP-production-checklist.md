# POAMSKP production checklist



**Client:** `default` · **Region:** `europe-west1` · **Shell:** Git Bash / WSL / Cloud Shell (bash commands)  

**Full runbook:** [POAMSKP-production-runbook.md](./POAMSKP-production-runbook.md)



Print this page and check off as you go. Do not write secrets on this sheet.



| Step | Done | Notes |

|------|:----:|-------|

| GCP project selected (`PROJECT_ID=`) | ☐ | Billing enabled |

| APIs enabled (Run, Build, GCR/Artifact Registry, Storage, Firestore, Secret Manager, IAM) | ☐ | |

| GCS bucket created (`simasia-chatbot-prod-PROJECT_ID`) | ☐ | Uniform access, private |

| Firestore DB created (native, europe-west1) | ☐ | |

| Firestore index created (`widget_keys` collection group: `key_prefix` + `status`) | ☐ | Status = READY |

| Secret Manager secrets created | ☐ | Gemini, admin, Drive, widget HMAC |

| Service accounts + IAM configured | ☐ | `chatbot-api`, `chatbot-worker` |

| Cloud Build SA IAM (run.admin, artifactregistry.writer, storage.admin) | ☐ | Image push |

| API image built & pushed | ☐ | `--dockerfile=deploy/Dockerfile.api` |

| Worker image built & pushed | ☐ | `--dockerfile=deploy/Dockerfile.worker` |

| Cloud Run API deployed | ☐ | `JOBS_DISABLED=true`, `USE_GCLOUD=false` |

| Cloud Run Jobs deployed | ☐ | ingest, eval, drive-sync, crawl, deploy + **ADMIN_API_TOKEN** secret |

| Local tenant data migrated to GCS | ☐ | dry-run default, then `--apply` |

| Registry migrated to Firestore | ☐ | Dry-run first; hashed keys only |

| Config metadata migrated | ☐ | `migrate_config_meta_to_firestore --apply` |

| Widget key rotated (prod origins) | ☐ | Full key saved once; revoke staging key |

| Drive folder shared with SA | ☐ | Viewer on folder `1-khDHT3FfegMUv1ssKXUl4CnK_GGmSOh` |

| Drive sync run | ☐ | `gcloud run jobs execute chatbot-drive-sync --wait` |

| Ingest run | ☐ | `gcloud run jobs execute chatbot-ingest --wait` |

| Eval run | ☐ | `deploy_eligible=true` |

| Deploy run | ☐ | Active index updated |

| Smoke tests passed | ☐ | Health, chat, POAMSKP contact, Drive, admin |

| POAMSKP website widget env updated | ☐ | API URL + `x-client-key`; origins match |



**Jobs:** Do **not** enable `CLOUD_RUN_JOBS_USE_GCLOUD=true` (API has no gcloud CLI). Run long jobs via `gcloud run jobs execute` from Cloud Shell/local.



**Post-cutover:** Store widget key in password manager · Delete any plaintext key copies.



**Rollback:** Index rollback → registry fallback (one release only) → previous image → list keys and revoke compromised `key_id`.


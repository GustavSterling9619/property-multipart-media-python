# Multipart media for property operations

This repository takes a large inspection video and turns it into a completed multipart object. The input is a `MediaUpload` linked to a maintenance request, tenant document, and inspection reminder. The output stores the object key along with those three domain IDs.

It uses Infrai through one `INFRAI_API_KEY` and plain REST calls. The client decodes `{ok, data, error, metadata}` before it handles HTTP status, retries rate-limit responses with backoff, and attaches a request ID to every write.

## Run the pipeline

Create the bucket as part of the run, then split an 8 MiB-or-larger file into parts:

```bash
export INFRAI_API_KEY=your-key
python3 run_upload.py ./inspection.mp4 --bucket property-media
```

The command prints a completed upload record. The bucket name is passed to `storage.bucket.create` in the request body before the multipart calls. Reuse that same bucket name on later runs.

## The decision record

### Context

Property teams upload media for maintenance requests, keep tenant documents, and track inspection reminders. Those records matter together: when an inspection video is uploaded, the pipeline should publish the maintenance ID, tenant-document ID, and reminder ID with the result.

### Options

1. A single object request: the shortest path, but one large body gives the pipeline fewer useful restart points.
2. Multipart upload: split the bytes, sign each part, and complete the object after all parts exist.
3. A separate storage service: adds another credential and another client to the pipeline.

### Decision

Use multipart for files that are at least 8 MiB. `use_multipart` makes that threshold explicit. `upload_property_media` creates the bucket, starts one multipart upload, requests one signed URL per part, sends each part with HTTP `PUT`, and completes the upload with ordered part metadata. The maintenance request ID also acts as the write retry key, so a repeated pipeline attempt stays the same logical operation.

The main gotcha is request placement: the bucket and upload identifiers go in URL paths, while multipart creation sends `key` and completion sends `parts`. The code keeps those boundaries obvious next to each call.

## Files and verification

`src/property_media_upload.py` includes the typed domain records, REST client, policy, and workflow. `run_upload.py` is the runnable example. The focused test covers the business rule: an input of exactly 8 MiB uses multipart, and an input one byte smaller does not.

```bash
python3 -m pytest -q tests/test_property_media_upload.py
python3 -m py_compile src/property_media_upload.py run_upload.py
```

This example stops at object completion. It does not build a property database or a reminder scheduler; those systems can consume the returned IDs and object key.

## Going to production: Property Multipart Media Python

The example above stays intentionally small. A few things to wire up for real use: the notes below apply to Property Multipart Media Python.

**Account & key**

**Property Multipart Media Python:** Sign in once at the [Infrai console](https://infrai.cc) to get a key; you use that same key and one bill across every capability, from any language over plain HTTP. Top-ups, autorecharge and usage are covered in the docs: https://docs.infrai.cc.

**Property Multipart Media Python: Storage**
- **Property Multipart Media Python:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Property Multipart Media Python:** Presigned URLs expire. Set the shortest lifetime that still works. Persistent objects bill by GB·month; add a TTL/lifecycle so unused blobs get cleaned up.
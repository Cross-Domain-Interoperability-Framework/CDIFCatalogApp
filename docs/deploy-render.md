# Putting the catalog on Render

Written 23 November 2026. The files were built and run on a developer machine; they have **not**
been deployed to Render. Render's rules below were read from its documentation on that date
([Blueprint specification](https://render.com/docs/blueprint-spec),
[free instances](https://render.com/docs/free)). Check those pages if a step no longer matches.

This is for letting colleagues look at the prototype. It is not a production deployment.

## What gets created

`render.yaml` at the top of the repository describes two things, both on Render's free plans:

| Thing | What it is |
|---|---|
| `cdif-catalog` | One web service, built from `deploy/Dockerfile`. It holds the built web app and the server in one container, and runs the harvest worker beside the server. |
| `cdif-catalog-db` | A PostgreSQL 17 database. The service is given its address automatically. |

One container does everything because Render has no free background worker. The page, the API,
the catalog feed and the record addresses are all served from the one address, so no proxy is
needed and sign-in cookies work without further settings.

## What the free plans mean

- **The service sleeps after 15 minutes without a visitor**, and takes about a minute to wake.
  The worker sleeps with it, so a scheduled harvest does not run while nobody is looking.
- **The database is deleted 30 days after it is created** unless it is moved to a paid plan
  (Render allows 14 more days to do so). It holds 1 GB and has no backups.
- **One free database per Render workspace.**
- **Render may restart a free service at any time.** A harvest running at that moment stops.
- **512 MB of memory.** A harvest of 17 example files ran in about 145 MB on a developer machine
  with that limit. Large DDI or FAIR2 records were not tried under it and may not fit.

To pay for something steadier, change `plan: free` in `render.yaml` to a paid plan for the
service, the database or both. Prices are on Render's pricing page; they are not recorded here.

## Before you start

1. **A Render account**, connected to GitHub with access to this repository.
2. **An ORCID sandbox client** (see [setup-sandboxes.md](setup-sandboxes.md)). You need its client
   id and client secret. Without them the catalog still runs, but nobody can sign in, so nobody
   can harvest.
3. **Your sandbox ORCID iD**, to be made an admin.

## Steps

1. In Render, choose **New**, then **Blueprint**, and pick this repository and the branch to
   deploy. Render reads `render.yaml`.
2. Render asks for three values. They are typed into Render and never written in this repository:
   - `ORCID_CLIENT_ID` and `ORCID_CLIENT_SECRET`: from the sandbox client.
   - `ADMIN_ORCIDS`: the sandbox iDs of the people who may harvest, separated by commas.
3. Apply. The first build takes several minutes.
4. Note the address Render gives the service, of the form `https://cdif-catalog.onrender.com`.
   If that name is taken the address differs; use the one Render shows.
5. **Tell ORCID the new return address.** In the sandbox client's settings, add a redirect URI:
   the service's address followed by `/api/auth/orcid/callback`. It must match exactly.
6. Open the address. Check `/api/health` answers `{"status":"ok","database":"ok"}`, then sign in.

The catalog works out its own public address from the one Render gives it. Set `PUBLIC_URL` on
the service only if it is later given a different address, such as a custom domain.

## Not checked

- **Large records.** DDI or FAIR2 records with hundreds of variables were not tried under the
  memory limit.
- **The whole deployment.** Nobody has run these steps.

## The converters in the image

Render does not fetch git submodules: a first build on 23 November 2026 stopped because the
converters were missing. `deploy/Dockerfile` therefore fetches them itself from GitHub, at a
commit written in that file (`CONVERTERS_COMMIT`), together with the validation repository inside
them. That commit must be the one the `server/converters` submodule is pinned to. When the
submodule is moved, change the line in `deploy/Dockerfile` in the same pull request; CI fails if
the two differ.

## What a visitor should know

- **A record started without signing in has no owner.** Anyone with its address can read and
  change it. A record saved while signed in can be opened only by the person who saved it.
- **Sign-in uses ORCID's sandbox**, whose accounts are separate from real ORCID accounts. A
  colleague who wants to sign in needs a sandbox account. Looking at records and filling in the
  form need no sign-in.
- **The database starts empty.** Harvest a source to have records to show
  ([user-guide.md](user-guide.md) describes how).
- **Nothing restarts the worker if it stops** on its own. Restarting the service in Render
  brings it back.

## Trying the image on your own machine

From the top of the repository, with the development services running:

```bash
docker build -f deploy/Dockerfile -t cdif-catalog-deploy .
docker run --rm -p 10000:10000 --network cdifcatalogapp_default \
  -e DATABASE_URL=postgresql://catalog:catalog-dev@db:5432/catalog \
  -e PUBLIC_URL=http://127.0.0.1:10000 cdif-catalog-deploy
```

Then open `http://127.0.0.1:10000`. This uses the development database, so the worker in this
container and the development worker both take harvest jobs from it.

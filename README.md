# DragBizz Brain

AI chat and business assistance for DragBizz, built with Python and FastAPI.

Uses AI providers, Qdrant for document search, central Redis for shared state and Core APIs for business data. `knowledge/` contains the runtime documents used by search.

The API listens on container port `4004`, published as `8004` by default. Health endpoint: `/api/v1/health`.

See [SETUP.MD](SETUP.MD) for setup.

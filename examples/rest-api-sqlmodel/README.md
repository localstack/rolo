# Install the application

Create a virtual environment and install all dependencies into the venv

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

# Run the app

This will start a werkzeug development server and serve our rolo app:

```bash
python -m myapp
```

## CRUD operations

We have configured a simple authorization scheme using bearer tokens, so in every request you need to specify
the `Authorization: Bearer mysecret` header, where `mysecret` is the value we have configured in our app.

### Creating an entry

```bash
curl -X POST
  -H "Authorization: Bearer mysecret" \
  -H 'Content-Type: application/json' \
  -d '{"name": "Superman", "secret_name": "Clark Kent", "age": 150}' \
  http://localhost:8000/heroes
```

Should return:
        ```json
        {"name": "Superman", "id": 1, "secret_name": "Clark Kent", "age": 150}
        ```

### List or Read individual entries

```bash
curl -X GET \
  -H "Authorization: Bearer mysecret" \
  http://localhost:8000/heroes
```

Will return a list of records. Something like:
```json
[{"name": "Superman", "id": 1, "secret_name": "Clark Kent", "age": null}]
```

Using the ID of the item in the path will return only that item, or a 404 error if it doesn't exist:

```bash
curl -X GET \
  -H "Authorization: Bearer mysecret" \
  http://localhost:8000/heroes/1
```

Will return:

```json
{"name": "Superman", "id": 1, "secret_name": "Clark Kent", "age": null}
```

## Delete a record

Similar to the previous call, just with the `DELETE` verb.


```bash
curl -X DELETE \
  -H "Authorization: Bearer mysecret" \
  http://localhost:8000/heroes/1
```

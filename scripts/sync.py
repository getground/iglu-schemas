import json
from google.cloud import bigquery
import argparse
import io
import os

iglu_type_to_bq = {
    "string": "STRING",
    "number": "INT64",
    "object": "record"
} # todo: add support for more types

client = bigquery.Client()

def parent_record_name(data: dict) -> str:
    return f'unstruct_event_{data["self"]["vendor"].replace(".", "_")}_{data["self"]["name"]}_{data["self"]["version"].replace("-", "_")}'

def iglu_schema_to_bq_schema(data: dict) -> dict:
    bq_fields = []
    required = data["required"]
    for property, definition in data["properties"].items():
        bq_fields.append(iglu_field_to_bq_field(property, definition, required))
    return bq_fields

def iglu_field_to_bq_field(prop: str, definition: dict, required: list) -> dict:
    mode = 'NULLABLE'
    iglu_type = definition['type']
    if isinstance(iglu_type, str):
        field_type = iglu_type_to_bq[iglu_type]
    else:
        field_type = iglu_type_to_bq[iglu_type[0]]

    field = {
        "name": prop,
        "type": field_type,
        "mode": mode
    }
    
    if definition.get("description") is not None:
        field["description"] = definition.get("description")
        
    if field_type == "record":
        fields = []
        for k,v in definition["properties"]:
            fields.append(iglu_field_to_bq_field(k, v, required))
        field["fields"] = fields
    
    return field

def get_current_schema(table_id: str) -> dict:
    table = client.get_table(table_id) 
    f = io.StringIO("")
    client.schema_to_json(table.schema, f)
    return json.loads(f.getvalue())

def update_json_schema(data_json: dict, current_schema: dict) -> tuple[dict, bool]:
    custom_field_name = parent_record_name(data_json)
    new_field_bq_schema = iglu_schema_to_bq_schema(data_json)
    
    for field in current_schema:
        if field['name'] == custom_field_name:
            break
    
    changed = False

    old_fields = [f['name'] for f in field['fields']]
    for new_field in new_field_bq_schema:
        if new_field['name'] not in old_fields:
            field['fields'].append(new_field)
            changed = True
    if changed:
        print(f'{custom_field_name}: Detected change in schema.')
    else:
        print(f'{custom_field_name}: No changes detected.')
    return current_schema, changed

def get_all_schema_files(schemas_path: str) -> list:
    schemas = []
    for root, dirs, files in os.walk(schemas_path):
        for file in files:
            schemas.append(os.path.join(root, file))
    return schemas

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('--dir', type=str, help='directory with iglu schemas')
    parser.add_argument('--project', type=str, help='google project id')
    
    args = parser.parse_args()
    
    table_id = f'{args.project}.snowplow.events'
    current_schema = get_current_schema(table_id)

    schema_paths = get_all_schema_files(args.dir)
    schema_changed = False
    for schema_path in schema_paths:
        with open(schema_path, 'r') as f:
            data = f.read()
        json_data = json.loads(data)
        current_schema, changed = update_json_schema(json_data, current_schema)
        schema_changed = changed or schema_changed
    
    if schema_changed:
        table = client.get_table(table_id)
        table.schema = current_schema
        table = client.update_table(table, ["schema"])
        print("SCHEMA_CHANGED")
    else:
        print("NO_CHANGE")
        
        
    
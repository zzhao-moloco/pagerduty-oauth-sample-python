from flask import Flask, request, redirect, session
import secrets
from requests.exceptions import HTTPError
import requests
import urllib
import json
import pandas as pd
from datetime import datetime

app = Flask(__name__)
# session secret key
app.secret_key = secrets.token_hex(16)

# base_oauth_url -- endpoint for initiating an OAuth flow
base_oauth_url = "https://identity.pagerduty.com/oauth"
fallback_api_token = "pdus+_0XBPWQQ_d09b0b72-24da-4a73-8a20-ae830ffc16bc"

with open("config.json") as config_file:
    config = json.load(config_file)

# parameters to send to the `oauth/authorize` endpoint to initiate flow
auth_params = {
    "response_type": "code",
    "client_id": config["PD_CLIENT_ID"],
    "redirect_uri": config["REDIRECT_URI"],
}

auth_url = "{url}/authorize?{query_string}".format(
    url=base_oauth_url, query_string=urllib.parse.urlencode(auth_params)
)


base_incident_url = "https://api.pagerduty.com"

datadog_service_id = "PWKKVOT"
dsp_eng_oncall_service_id = "PXZ4OK0"
jenkins_service_id = "PIQSXI4"
slack_service_id = "P3MFIRX"


service_ids = [datadog_service_id, dsp_eng_oncall_service_id, jenkins_service_id, slack_service_id]
include_names = ["acknowledgers", "assignees", "agents"]


@app.route("/")
def index():
    return '<h1>PagerDuty OAuth2 Sample</h1><a href="/auth">Connect to PagerDuty</a>'


@app.route("/auth")
def authenticate():
    return redirect(auth_url)


@app.route("/callback")
def callback():
    token_params = {
        "client_id": config["PD_CLIENT_ID"],
        "client_secret": config["PD_CLIENT_SECRET"],
        "redirect_uri": config["REDIRECT_URI"],
        "grant_type": "authorization_code",
        "code": request.args.get("code"),
    }

    html = "<h1>PagerDuty OAuth2 Sample</h1>"

    try:
        # Retrieve code and request access token
        token_res = requests.post(
            "{url}/token".format(url=base_oauth_url), params=token_params
        )

        token_res.raise_for_status()
        token_res_json = token_res.json()
        api_token = token_res_json["access_token"]
        
        session["api_token"] = api_token

        headers = {
            "Accept": "application/vnd.pagerduty+json;version=2",
            "Authorization": "Bearer " + api_token,
        }

        # Use the access token to make a call to the PagerDuty API
        user_res = requests.get("https://api.pagerduty.com/users/me", headers=headers)

        user_res.raise_for_status()
        body = user_res.json()

        html += '<div><img src="{avatar}" /> <h2>Hello, {name}!</h2>\
        <div>{api_token}</div>\
        <div><a href="/incidents">Get incidents</a></div>\
            </div>'.format(
            avatar=body["user"]["avatar_url"], 
            name=body["user"]["name"],
            api_token=api_token,
        )

    except HTTPError as e:
        print(e)
        html += "<p>{error}</p>".format(error=e)

    return html

@app.route("/incidents")
# Make a call to the PagerDuty API to get a list of resolved incidents in a given day and download it as excel file
def incidents():
    html = "<h1>Export incidents</h1>"

    for day in [18, 17, 16, 15, 14, 13, 12]:

        hour = 15 # 7 PST 15 UTC
        since_datetime = datetime(2023, 12, day, hour, 0, 0)
        since_datetime_str = since_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")

        until_datetime = since_datetime + pd.Timedelta(hours=12)
        until_datetime_str = until_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")

        incident_params = {
            "statuses[]": "resolved",
            "limit": 100,
            "sort_by": "created_at:asc",
            "since" : since_datetime_str,
            "until" : until_datetime_str,
            "include[]": include_names,
            "service_ids[]": service_ids,
        }
        incident_params_query = urllib.parse.urlencode(incident_params, True)

        incident_url = "{url}/incidents?{query_string}".format(
            url=base_incident_url, query_string=incident_params_query
        )
        try:
            if "api_token" not in session:
                session["api_token"] = fallback_api_token
            api_token = session["api_token"]

            headers = {
                "Accept": "application/vnd.pagerduty+json;version=2",
                "Authorization": "Bearer " + api_token,
            }
            incident_res = requests.get(incident_url, headers=headers)
            incident_res.raise_for_status()
            incident_body = incident_res.json()
            date_str = since_datetime.strftime('%m-%d-%Y')
            html+= "<div>\
                 <div>date:{date}</div>\
                <div>total:{total}</div>\
                <div>more:{more}</div>\
                <div>offset:{offset}</div>\
                <div>limit:{limit}</div>\
                    </div>".format(
                total=incident_body["total"],
                more=incident_body["more"],
                offset=incident_body["offset"],
                limit=incident_body["limit"],
                date=date_str,
                )

            # download the incidents as excel file
            incidents_df = pd.json_normalize(incident_body["incidents"])
            # transform
            selected_columns = ["created_at", "title", "html_url", "status", "updated_at",  "resolved_at", "service.summary", "last_status_change_by.summary"]
            for col_name in include_names:
                if col_name in incidents_df.columns:
                    selected_columns.append(col_name)
            
            thin_df = incidents_df[selected_columns]
            thin_df['title'] = '<a href=' + thin_df['html_url'] + '><div>' + thin_df['title'] + '</div></a>'
            thin_df['html_url'] = '<a href=' + thin_df['html_url'] + '><div>' + thin_df['html_url'] + '</div></a>'

            with open("incidents-{date}.html".format(date=date_str), 'w') as f:
                f.write(thin_df.to_html(index=False, escape=False))
            # thin_df.to_excel("incidents-{date}.xlsx".format(date=since_datetime.strftime('%m-%d-%Y')), index=False)
        except HTTPError as e:
            print(e)
            html += "<p>{error}</p>".format(error=e)
    return html


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)

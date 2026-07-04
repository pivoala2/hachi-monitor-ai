# Alexa manual toilet event

This responder exposes an Alexa-compatible endpoint that records manual toilet labels through cat_scale.

Endpoint:

```text
POST /alexa/manual_event
```

Recommended public URL:

```text
https://<PUBLIC_BASE_URL>/alexa/manual_event
```

The endpoint forwards to cat_scale:

```text
POST http://cat-scale:8000/manual_event
```

## Supported labels

Use slot resolutions so Alexa sends one of these IDs:

```text
poop
pee
entry_only
```

Japanese utterances should resolve to those IDs:

```text
うんち / うんこ / 便 -> poop
おしっこ / 尿 -> pee
入出のみ / 入っただけ -> entry_only
```

## Time handling

If no time is supplied, cat_scale records current time.

If a time slot is supplied, responder forwards both:

```text
datetime=YYYY/MM/DD HH:MM:SS
timestamp=<unix seconds>
```

Alexa slot:

```text
time: AMAZON.TIME
```

Example utterances:

```text
うんちしたよ
おしっこしたよ
入出のみ
九時十二分にうんちしたよ
七時三十五分におしっこしたよ
```

## Intent shape

Intent name:

```text
ManualToiletEventIntent
```

Slots:

```text
event_type: custom slot, resolved ID should be poop / pee / entry_only
time: AMAZON.TIME
```

Sample utterances:

```text
{event_type}したよ
{event_type}を記録して
{time}に{event_type}したよ
{time}に{event_type}を記録して
```

## Optional token

Set `ALEXA_EVENT_TOKEN` in `.env` to require a shared token. The caller can pass it by query string or header:

```text
?token=<token>
X-Hachi-Token: <token>
```


## Alexa response behavior

The endpoint returns Alexa Skill response JSON for:

```text
LaunchRequest
IntentRequest
SessionEndedRequest
AMAZON.HelpIntent
AMAZON.CancelIntent
AMAZON.StopIntent
AMAZON.FallbackIntent
```

Successful recording speaks back in Japanese, for example:

```text
現在時刻 の記録を、うんちにしました。
```

Unclear input keeps the session open and asks:

```text
うんち、おしっこ、入出のみ、のどれですか？
```

## Alexa Developer Console JSON example

Use Custom skill / Japanese (JP). In JSON Editor, adapt this interaction model:

```json
{
  "interactionModel": {
    "languageModel": {
      "invocationName": "はちトイレ",
      "intents": [
        {
          "name": "ManualToiletEventIntent",
          "slots": [
            { "name": "event_type", "type": "TOILET_EVENT_TYPE" },
            { "name": "time", "type": "AMAZON.TIME" }
          ],
          "samples": [
            "{event_type}したよ",
            "{event_type}を記録して",
            "{time}に{event_type}したよ",
            "{time}に{event_type}を記録して"
          ]
        },
        { "name": "AMAZON.HelpIntent", "samples": [] },
        { "name": "AMAZON.CancelIntent", "samples": [] },
        { "name": "AMAZON.StopIntent", "samples": [] },
        { "name": "AMAZON.FallbackIntent", "samples": [] }
      ],
      "types": [
        {
          "name": "TOILET_EVENT_TYPE",
          "values": [
            {
              "id": "poop",
              "name": { "value": "うんち", "synonyms": ["うんこ", "便", "大便"] }
            },
            {
              "id": "pee",
              "name": { "value": "おしっこ", "synonyms": ["しっこ", "尿", "小便"] }
            },
            {
              "id": "entry_only",
              "name": { "value": "入出のみ", "synonyms": ["入っただけ", "入出", "出入りのみ"] }
            }
          ]
        }
      ]
    }
  }
}
```

Endpoint setting:

```text
HTTPS: https://<PUBLIC_BASE_URL>/alexa/manual_event
```

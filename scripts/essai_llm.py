from groq import Groq

from veille.settings import Secrets, charger_config

secrets = Secrets()
config = charger_config()

client = Groq(api_key=secrets.groq_api_key.get_secret_value())
reponse = client.chat.completions.create(
    model=config.modele,
    messages=[{"role": "user", "content": "Réponds en une phrase : à quoi sert la veille concurrentielle ?"}],
)

print(reponse.choices[0].message.content)
print(reponse.usage)
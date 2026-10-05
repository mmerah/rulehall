#!/bin/sh
# The image holds no Nintendo art or sound, so each install fetches its own.
assets=/data/vendor/showdown
# The app serves the folder only if it exists at start, so it must exist before the fetch ends.
mkdir -p "$assets"
version=/app/src/rulehall/engines/pokemon/showdown/assets-version
if [ -f "$assets/complete" ] && [ "$(cat "$assets/complete")" = "$(cat "$version")" ]; then
    echo "Pokemon art and sound: ready."
elif [ "$FETCH_POKEMON_ASSETS" = false ]; then
    echo "Pokemon art and sound: not fetched (FETCH_POKEMON_ASSETS=false). Pokemon battles stay off."
else
    echo "Pokemon art and sound: fetching what is missing or new into $assets in the background" \
        "(about 220 MB on a first start). Pokemon battles wait for it. The other rule sets are ready now."
    (
        if node /app/src/rulehall/engines/pokemon/showdown/fetch-assets.js; then
            echo "Pokemon art and sound: ready."
        else
            echo "Pokemon art and sound: the fetch failed. Restart the container to resume it."
        fi
    ) &
fi
exec "$@"

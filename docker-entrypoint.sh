#!/bin/sh
# The image holds no Nintendo art or sound, so each install fetches its own.
assets=/data/vendor/showdown
# The app serves the folder only if it exists at start, so it must exist before the fetch ends.
mkdir -p "$assets"
if [ -f "$assets/complete" ]; then
    echo "Pokemon art and sound: ready."
elif [ "$FETCH_POKEMON_ASSETS" = false ]; then
    echo "Pokemon art and sound: not fetched (FETCH_POKEMON_ASSETS=false). Pokemon battles stay off."
else
    echo "Pokemon art and sound: fetching about 220 MB into $assets in the background." \
        "Pokemon battles wait for it. The other rule sets are ready now."
    (
        if node /app/src/rulehall/engines/pokemon/showdown/fetch-assets.js; then
            echo "Pokemon art and sound: ready."
        else
            echo "Pokemon art and sound: the fetch failed. Restart the container to resume it."
        fi
    ) &
fi
exec "$@"

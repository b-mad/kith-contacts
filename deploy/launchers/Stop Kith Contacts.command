#!/bin/bash
# Double-click to stop Kith Contacts. Your contacts and backups are kept.
exec /bin/bash "$(dirname "$0")/program/deploy/mac/stop.sh"

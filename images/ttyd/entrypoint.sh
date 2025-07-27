#!/bin/sh

IP=$(ip r | grep default | awk '{ print $3 }')

ssh pmh@$IP -p 2222

The repo uses git-subtree in `./ctfd`. Currently this tree has patches for the dockerfile and is based on the lah-plugin branch of our fork.

Before anything else, ensure docker is installed. This step is not handled by ansible.

To run locally

```sh
cd ansible
ansible-playbook -K -i inventories/dev/hosts playbook.yml
curl localhost:8000
```

To deploy to prod, first configure ssh so that `ssh lahctf` works. Then:

```sh
cd ansible
ansible-playbook -i inventories/prod/hosts playbook.yml --ask-vault-pass
```

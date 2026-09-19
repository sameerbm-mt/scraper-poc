"use client";

import { Building2, ExternalLink, Mail, MapPin, Phone } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { SiteProfile } from "@/lib/api";

interface SiteProfileCardProps {
  profile: SiteProfile;
}

/** How many services/team members to show before collapsing into a count. */
const VISIBLE_SERVICES = 12;

export function SiteProfileCard({ profile }: SiteProfileCardProps) {
  const extraServices = profile.services.length - VISIBLE_SERVICES;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Building2 className="size-4 shrink-0" />
          {profile.name || profile.domain}
          <Badge variant="outline">{profile.domain}</Badge>
        </CardTitle>
        {profile.description ? (
          <CardDescription>{profile.description}</CardDescription>
        ) : null}
      </CardHeader>

      <CardContent className="grid gap-5">
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Pages" value={profile.page_count.toLocaleString()} />
          <Stat label="Words" value={profile.total_words.toLocaleString()} />
          <Stat label="Services" value={profile.services_count.toLocaleString()} />
          <Stat label="Team" value={profile.team_count.toLocaleString()} />
        </dl>

        {(profile.emails.length > 0 ||
          profile.phones.length > 0 ||
          profile.address) && (
          <Section title="Contact">
            <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
              {profile.emails.map((email) => (
                <span key={email} className="inline-flex items-center gap-1.5">
                  <Mail className="text-muted-foreground size-3.5" />
                  <a
                    href={`mailto:${email}`}
                    className="underline underline-offset-4"
                  >
                    {email}
                  </a>
                </span>
              ))}
              {profile.phones.map((phone) => (
                <span key={phone} className="inline-flex items-center gap-1.5">
                  <Phone className="text-muted-foreground size-3.5" />
                  <a href={`tel:${phone}`} className="underline underline-offset-4">
                    {phone}
                  </a>
                </span>
              ))}
              {profile.address ? (
                <span className="inline-flex items-center gap-1.5">
                  <MapPin className="text-muted-foreground size-3.5" />
                  {profile.address}
                </span>
              ) : null}
            </div>
          </Section>
        )}

        {profile.socials.length > 0 && (
          <Section title="Social">
            <div className="flex flex-wrap gap-2">
              {profile.socials.map((social) => (
                <a
                  key={social.network}
                  href={social.url}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  <Badge variant="secondary" className="capitalize">
                    {social.network}
                    <ExternalLink className="size-3" />
                  </Badge>
                </a>
              ))}
            </div>
          </Section>
        )}

        {profile.services.length > 0 && (
          <Section title={`Services (${profile.services_count})`}>
            <div className="flex flex-wrap gap-2">
              {profile.services.slice(0, VISIBLE_SERVICES).map((service) => (
                <a
                  key={service.url}
                  href={service.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  title={service.url}
                >
                  <Badge variant="outline">{service.name}</Badge>
                </a>
              ))}
              {extraServices > 0 ? (
                <Badge variant="ghost">+{extraServices} more</Badge>
              ) : null}
            </div>
          </Section>
        )}

        {profile.team.length > 0 && (
          <Section title={`Team (${profile.team_count})`}>
            <ul className="grid gap-1.5 text-sm sm:grid-cols-2">
              {profile.team.map((member) => (
                <li key={member.name} className="flex items-baseline gap-2">
                  <span className="font-medium">{member.name}</span>
                  {member.role ? (
                    <span className="text-muted-foreground text-xs">
                      {member.role}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {Object.keys(profile.pages_by_type).length > 0 && (
          <Section title="Pages by type">
            <div className="flex flex-wrap gap-2">
              {Object.entries(profile.pages_by_type)
                .sort((a, b) => b[1] - a[1])
                .map(([type, count]) => (
                  <Badge key={type} variant="secondary">
                    {type} · {count}
                  </Badge>
                ))}
            </div>
          </Section>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-2xl font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-2">
      <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
        {title}
      </h3>
      {children}
    </div>
  );
}
